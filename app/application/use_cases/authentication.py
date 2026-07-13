from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.application.ports.auth import AccessTokenService, OpaqueTokenService, PasswordHasher
from app.application.ports.messaging import EmailMessage, EmailProvider
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
from app.application.services.authentication import (
    DEFAULT_ACCESS_TOKEN_TTL,
    DEFAULT_INVITATION_TOKEN_TTL,
    DEFAULT_PASSWORD_RESET_TOKEN_TTL,
    DEFAULT_REFRESH_TOKEN_TTL,
    DEFAULT_SIGNIN_LOCKOUT_WINDOW,
    DEFAULT_SIGNIN_MAX_FAILED_ATTEMPTS,
    AuthIdentityContext,
    IssuedSessionTokens,
    allowed_permissions,
    is_active_workspace_membership_context,
    issue_access_token,
    issue_session_tokens,
    list_identity_contexts_for_user,
    normalize_email_address,
    render_invitation_email_body,
    revoke_user_refresh_sessions,
)
from app.application.services.refresh_sessions import (
    RefreshSessionUseReason,
    evaluate_refresh_session_for_use,
    rotate_refresh_session,
)
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    AuthenticatedActor,
    PasswordCredential,
    PasswordPolicyReasonCode,
    PasswordResetToken,
    PermissionCapability,
    RefreshSessionRevocationReason,
    User,
    UserInvitation,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
    evaluate_password_policy,
    evaluate_permission,
)


class AuthReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    INVALID_EMAIL = "invalid_email"
    INVALID_ROLE = "invalid_role"
    FULL_NAME_REQUIRED = "full_name_required"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    WORKSPACE_CONTEXT_MISMATCH = "workspace_context_mismatch"
    MEMBERSHIP_ALREADY_ACTIVE = "membership_already_active"
    INVITATION_NOT_FOUND = "invitation_not_found"
    INVITATION_EXPIRED = "invitation_expired"
    INVITATION_ALREADY_ACCEPTED = "invitation_already_accepted"
    INVITATION_REVOKED = "invitation_revoked"
    PASSWORD_POLICY_FAILED = "password_policy_failed"
    INVALID_CREDENTIALS = "invalid_credentials"
    USER_NOT_ACTIVE = "user_not_active"
    USER_DISABLED = "user_disabled"
    USER_LOCKED = "user_locked"
    WORKSPACE_SELECTION_REQUIRED = "workspace_selection_required"
    WORKSPACE_MEMBERSHIP_NOT_FOUND = "workspace_membership_not_found"
    WORKSPACE_NOT_ACTIVE = "workspace_not_active"
    MEMBERSHIP_NOT_ACTIVE = "membership_not_active"
    REFRESH_TOKEN_INVALID = "refresh_token_invalid"
    REFRESH_SESSION_EXPIRED = "refresh_session_expired"
    REFRESH_SESSION_REVOKED = "refresh_session_revoked"
    REFRESH_TOKEN_REUSE_DETECTED = "refresh_token_reuse_detected"
    RESET_TOKEN_NOT_FOUND = "reset_token_not_found"
    RESET_TOKEN_EXPIRED = "reset_token_expired"
    RESET_TOKEN_ALREADY_USED = "reset_token_already_used"
    USER_NOT_FOUND = "user_not_found"


class InviteWorkspaceUserStatus(StrEnum):
    INVITED = "invited"
    REJECTED = "rejected"


class CompleteInvitedSignupStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"


class SignInStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    REJECTED = "rejected"


class RefreshAuthenticationStatus(StrEnum):
    REFRESHED = "refreshed"
    REJECTED = "rejected"


class LogoutStatus(StrEnum):
    LOGGED_OUT = "logged_out"


class ForgotPasswordStatus(StrEnum):
    ACCEPTED = "accepted"


class ResetPasswordStatus(StrEnum):
    RESET = "reset"
    REJECTED = "rejected"


class CurrentUserStatus(StrEnum):
    FOUND = "found"
    REJECTED = "rejected"


class SwitchWorkspaceStatus(StrEnum):
    SWITCHED = "switched"
    REJECTED = "rejected"


@dataclass(frozen=True)
class InviteWorkspaceUserResult:
    status: InviteWorkspaceUserStatus
    user: User | None = None
    membership: WorkspaceMembership | None = None
    invitation: UserInvitation | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class CompleteInvitedSignupResult:
    status: CompleteInvitedSignupStatus
    user: User | None = None
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    tokens: IssuedSessionTokens | None = None
    reasons: tuple[AuthReasonCode, ...] = ()
    password_policy_reasons: tuple[PasswordPolicyReasonCode, ...] = ()


@dataclass(frozen=True)
class SignInResult:
    status: SignInStatus
    user: User | None = None
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    tokens: IssuedSessionTokens | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class RefreshAuthenticationResult:
    status: RefreshAuthenticationStatus
    user: User | None = None
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    tokens: IssuedSessionTokens | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class LogoutResult:
    status: LogoutStatus
    revoked: bool


@dataclass(frozen=True)
class ForgotPasswordResult:
    status: ForgotPasswordStatus


@dataclass(frozen=True)
class ResetPasswordResult:
    status: ResetPasswordStatus
    user: User | None = None
    reasons: tuple[AuthReasonCode, ...] = ()
    password_policy_reasons: tuple[PasswordPolicyReasonCode, ...] = ()


@dataclass(frozen=True)
class CurrentUserResult:
    status: CurrentUserStatus
    user: User | None = None
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    permissions: tuple[str, ...] = ()
    reasons: tuple[AuthReasonCode, ...] = ()


@dataclass(frozen=True)
class SwitchWorkspaceResult:
    status: SwitchWorkspaceStatus
    user: User | None = None
    workspace: Workspace | None = None
    membership: WorkspaceMembership | None = None
    access_token: str | None = None
    access_token_expires_at: datetime | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


async def invite_workspace_user(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    email: str,
    role: WorkspaceMembershipRole,
    full_name: str | None,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    invitation_repository: InvitationRepository,
    audit_log_repository: AuthAuditLogRepository,
    opaque_token_service: OpaqueTokenService,
    email_provider: EmailProvider,
    frontend_app_base_url: str,
    now: datetime,
    invitation_ttl: timedelta = DEFAULT_INVITATION_TOKEN_TTL,
) -> InviteWorkspaceUserResult:
    permission = evaluate_permission(actor, PermissionCapability.INVITE_WORKSPACE_USER)
    if not permission.allowed:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )
    if actor.active_workspace_id != workspace_id:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_CONTEXT_MISMATCH,),
        )
    if role not in _INVITABLE_WORKSPACE_ROLES:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_ROLE,),
        )

    try:
        email_normalized = normalize_email_address(email)
    except ValidationError:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_EMAIL,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )

    user = await user_repository.get_by_email_normalized(email_normalized)
    if user is None:
        user = User(
            user_id=uuid4(),
            email=email_normalized,
            email_normalized=email_normalized,
            full_name=_normalized_optional_text(full_name),
            status=UserStatus.PENDING_VERIFICATION,
            email_verified_at=None,
            created_at=now,
            updated_at=now,
        )
    elif full_name and user.full_name != full_name.strip():
        user = replace(
            user,
            full_name=full_name.strip(),
            updated_at=now,
        )
    saved_user = await user_repository.save(user)

    membership = await membership_repository.get_by_user_and_workspace(
        saved_user.user_id,
        workspace_id,
    )
    if membership is not None and membership.status == WorkspaceMembershipStatus.ACTIVE:
        return InviteWorkspaceUserResult(
            status=InviteWorkspaceUserStatus.REJECTED,
            user=saved_user,
            membership=membership,
            reasons=(AuthReasonCode.MEMBERSHIP_ALREADY_ACTIVE,),
        )

    membership = WorkspaceMembership(
        membership_id=membership.membership_id if membership is not None else uuid4(),
        workspace_id=workspace_id,
        user_id=saved_user.user_id,
        role=role,
        status=WorkspaceMembershipStatus.INVITED,
        created_at=membership.created_at if membership is not None else now,
        updated_at=now,
    )
    saved_membership = await membership_repository.save(membership)

    existing_invitation = await invitation_repository.get_by_workspace_and_email_normalized(
        workspace_id,
        email_normalized,
    )
    invitation_token = opaque_token_service.generate_token()
    invitation = UserInvitation(
        invitation_id=(
            existing_invitation.invitation_id if existing_invitation is not None else uuid4()
        ),
        workspace_id=workspace_id,
        user_id=saved_user.user_id,
        email=saved_user.email,
        email_normalized=saved_user.email_normalized,
        role=role,
        token_hash=invitation_token.token_hash,
        expires_at=now + invitation_ttl,
        accepted_at=None,
        revoked_at=None,
        created_by_user_id=actor.user_id,
        created_at=existing_invitation.created_at if existing_invitation is not None else now,
    )
    saved_invitation = await invitation_repository.save(invitation)

    await email_provider.send(
        EmailMessage(
            to_email=saved_user.email,
            subject=f"You're invited to {workspace.name}",
            body=render_invitation_email_body(
                workspace_name=workspace.name,
                role=role,
                invitation_token=invitation_token.plaintext,
                frontend_app_base_url=frontend_app_base_url,
            ),
            idempotency_key=f"auth-invitation:{saved_invitation.invitation_id}:{saved_invitation.expires_at.isoformat()}",
        ),
    )

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.USER_INVITED,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=saved_user.user_id,
            event_details={
                "role": role.value,
                "invitation_id": str(saved_invitation.invitation_id),
            },
        ),
    )
    return InviteWorkspaceUserResult(
        status=InviteWorkspaceUserStatus.INVITED,
        user=saved_user,
        membership=saved_membership,
        invitation=saved_invitation,
    )


async def complete_invited_signup(
    *,
    invitation_token: str,
    full_name: str,
    password: str,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    credential_repository: PasswordCredentialRepository,
    invitation_repository: InvitationRepository,
    refresh_session_repository: RefreshSessionRepository,
    audit_log_repository: AuthAuditLogRepository,
    password_hasher: PasswordHasher,
    access_token_service: AccessTokenService,
    opaque_token_service: OpaqueTokenService,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
    refresh_token_ttl: timedelta = DEFAULT_REFRESH_TOKEN_TTL,
) -> CompleteInvitedSignupResult:
    if not full_name.strip():
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.FULL_NAME_REQUIRED,),
        )

    invitation = await invitation_repository.get_by_token_hash_for_update(
        opaque_token_service.hash_token(invitation_token),
    )
    validation_reason = _validate_invitation(invitation, now)
    if validation_reason is not None:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(validation_reason,),
        )
    assert invitation is not None

    password_decision = evaluate_password_policy(password)
    if not password_decision.accepted:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.PASSWORD_POLICY_FAILED,),
            password_policy_reasons=password_decision.reasons,
        )

    user = await user_repository.get_by_id(invitation.user_id)
    workspace = await workspace_repository.get_by_id(invitation.workspace_id)
    membership = await membership_repository.get_by_user_and_workspace(
        invitation.user_id,
        invitation.workspace_id,
    )
    if user is None or workspace is None or membership is None:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )
    if workspace.status != WorkspaceStatus.ACTIVE:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_ACTIVE,),
        )
    if membership.status == WorkspaceMembershipStatus.ACTIVE:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.MEMBERSHIP_ALREADY_ACTIVE,),
        )
    if membership.status != WorkspaceMembershipStatus.INVITED:
        return CompleteInvitedSignupResult(
            status=CompleteInvitedSignupStatus.REJECTED,
            reasons=(AuthReasonCode.MEMBERSHIP_NOT_ACTIVE,),
        )

    saved_user = await user_repository.save(
        replace(
            user,
            full_name=full_name.strip(),
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            updated_at=now,
        ),
    )
    saved_membership = await membership_repository.save(
        replace(
            membership,
            status=WorkspaceMembershipStatus.ACTIVE,
            updated_at=now,
        ),
    )

    existing_credential = await credential_repository.get_by_user_id_for_update(saved_user.user_id)
    password_hash = password_hasher.hash_password(password)
    credential = PasswordCredential(
        user_id=saved_user.user_id,
        password_hash=password_hash,
        password_changed_at=now,
        failed_attempt_count=0,
        locked_until=None,
        created_at=existing_credential.created_at if existing_credential is not None else now,
        updated_at=now,
    )
    await credential_repository.save(credential)

    accepted_invitation = replace(invitation, accepted_at=now)
    saved_invitation = await invitation_repository.save(accepted_invitation)

    identity = AuthIdentityContext(
        user=saved_user,
        workspace=workspace,
        membership=saved_membership,
    )
    tokens = await issue_session_tokens(
        identity=identity,
        access_token_service=access_token_service,
        opaque_token_service=opaque_token_service,
        refresh_session_repository=refresh_session_repository,
        now=now,
        access_token_ttl=access_token_ttl,
        refresh_token_ttl=refresh_token_ttl,
    )

    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.INVITATION_ACCEPTED,
            now=now,
            workspace_id=workspace.workspace_id,
            actor_user_id=saved_user.user_id,
            subject_user_id=saved_user.user_id,
            event_details={"invitation_id": str(saved_invitation.invitation_id)},
        ),
    )
    return CompleteInvitedSignupResult(
        status=CompleteInvitedSignupStatus.COMPLETED,
        user=saved_user,
        workspace=workspace,
        membership=saved_membership,
        tokens=tokens,
    )


async def sign_in(
    *,
    email: str,
    password: str,
    workspace_id: UUID | None,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    credential_repository: PasswordCredentialRepository,
    refresh_session_repository: RefreshSessionRepository,
    audit_log_repository: AuthAuditLogRepository,
    password_hasher: PasswordHasher,
    access_token_service: AccessTokenService,
    opaque_token_service: OpaqueTokenService,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
    refresh_token_ttl: timedelta = DEFAULT_REFRESH_TOKEN_TTL,
    signin_max_failed_attempts: int = DEFAULT_SIGNIN_MAX_FAILED_ATTEMPTS,
    lockout_window: timedelta = DEFAULT_SIGNIN_LOCKOUT_WINDOW,
) -> SignInResult:
    try:
        email_normalized = normalize_email_address(email)
    except ValidationError:
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_CREDENTIALS,),
        )

    user = await user_repository.get_by_email_normalized(email_normalized)
    if user is None:
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_CREDENTIALS,),
        )
    if user.status == UserStatus.DISABLED:
        await audit_log_repository.append(
            _auth_audit_log(
                event_type=AuthAuditEventType.SIGNIN_FAILED,
                now=now,
                subject_user_id=user.user_id,
                event_details={"reason": AuthReasonCode.USER_DISABLED.value},
            ),
        )
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.USER_DISABLED,),
        )

    credential = await credential_repository.get_by_user_id_for_update(user.user_id)
    if credential is None:
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_CREDENTIALS,),
        )

    user, credential, cleared_expired_lock = _clear_expired_lock(
        user=user,
        credential=credential,
        now=now,
    )
    if credential.locked_until is not None and credential.locked_until > now:
        await audit_log_repository.append(
            _auth_audit_log(
                event_type=AuthAuditEventType.SIGNIN_FAILED,
                now=now,
                subject_user_id=user.user_id,
                event_details={"reason": AuthReasonCode.USER_LOCKED.value},
            ),
        )
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.USER_LOCKED,),
        )

    if not password_hasher.verify_password(password, credential.password_hash):
        failed_count = credential.failed_attempt_count + 1
        locked_until = None
        user_status = user.status
        if failed_count >= signin_max_failed_attempts:
            locked_until = now + lockout_window
            user_status = UserStatus.LOCKED
        saved_credential = await credential_repository.save(
            replace(
                credential,
                failed_attempt_count=failed_count,
                locked_until=locked_until,
                updated_at=now,
            ),
        )
        if user_status != user.status:
            await user_repository.save(
                replace(user, status=user_status, updated_at=now),
            )
        await audit_log_repository.append(
            _auth_audit_log(
                event_type=AuthAuditEventType.SIGNIN_FAILED,
                now=now,
                subject_user_id=user.user_id,
                event_details={
                    "reason": AuthReasonCode.INVALID_CREDENTIALS.value,
                    "failed_attempt_count": str(saved_credential.failed_attempt_count),
                },
            ),
        )
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.INVALID_CREDENTIALS,),
        )

    if user.status not in {UserStatus.ACTIVE, UserStatus.LOCKED}:
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_ACTIVE,),
        )

    identity, reason = await _resolve_signin_identity(
        user=user,
        requested_workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if identity is None:
        return SignInResult(
            status=SignInStatus.REJECTED,
            reasons=(reason,),
        )

    saved_user = user
    if user.status == UserStatus.LOCKED:
        saved_user = await user_repository.save(
            replace(user, status=UserStatus.ACTIVE, updated_at=now),
        )
    elif cleared_expired_lock and user.status == UserStatus.ACTIVE:
        saved_user = await user_repository.save(user)

    should_update_credential = (
        cleared_expired_lock
        or credential.failed_attempt_count > 0
        or credential.locked_until is not None
        or password_hasher.needs_rehash(credential.password_hash)
    )
    if should_update_credential:
        new_hash = credential.password_hash
        if password_hasher.needs_rehash(credential.password_hash):
            new_hash = password_hasher.hash_password(password)
        await credential_repository.save(
            replace(
                credential,
                password_hash=new_hash,
                password_changed_at=(
                    now if new_hash != credential.password_hash else credential.password_changed_at
                ),
                failed_attempt_count=0,
                locked_until=None,
                updated_at=now,
            ),
        )

    resolved_identity = replace(identity, user=saved_user)
    tokens = await issue_session_tokens(
        identity=resolved_identity,
        access_token_service=access_token_service,
        opaque_token_service=opaque_token_service,
        refresh_session_repository=refresh_session_repository,
        now=now,
        access_token_ttl=access_token_ttl,
        refresh_token_ttl=refresh_token_ttl,
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.SIGNIN_SUCCEEDED,
            now=now,
            workspace_id=resolved_identity.workspace.workspace_id,
            actor_user_id=saved_user.user_id,
            subject_user_id=saved_user.user_id,
            event_details={"membership_id": str(resolved_identity.membership.membership_id)},
        ),
    )
    return SignInResult(
        status=SignInStatus.AUTHENTICATED,
        user=saved_user,
        workspace=resolved_identity.workspace,
        membership=resolved_identity.membership,
        tokens=tokens,
    )


async def refresh_authentication(
    *,
    refresh_token: str,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    refresh_session_repository: RefreshSessionRepository,
    access_token_service: AccessTokenService,
    opaque_token_service: OpaqueTokenService,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
    refresh_token_ttl: timedelta = DEFAULT_REFRESH_TOKEN_TTL,
) -> RefreshAuthenticationResult:
    session = await refresh_session_repository.get_by_token_hash_for_update(
        opaque_token_service.hash_token(refresh_token),
    )
    if session is None:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.REFRESH_TOKEN_INVALID,),
        )

    decision = evaluate_refresh_session_for_use(session, now=now)
    if decision.reason == RefreshSessionUseReason.REUSE_DETECTED:
        await revoke_user_refresh_sessions(
            user_id=session.user_id,
            refresh_session_repository=refresh_session_repository,
            reason=RefreshSessionRevocationReason.REUSE_DETECTED,
            now=now,
            family_id=session.family_id,
        )
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.REFRESH_TOKEN_REUSE_DETECTED,),
        )
    if decision.reason == RefreshSessionUseReason.EXPIRED:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.REFRESH_SESSION_EXPIRED,),
        )
    if not decision.accepted:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.REFRESH_SESSION_REVOKED,),
        )

    user = await user_repository.get_by_id(session.user_id)
    if user is None:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
        )
    if user.status != UserStatus.ACTIVE:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_ACTIVE,),
        )
    identity, reason = await _resolve_signin_identity(
        user=user,
        requested_workspace_id=session.workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if identity is None:
        return RefreshAuthenticationResult(
            status=RefreshAuthenticationStatus.REJECTED,
            reasons=(reason,),
        )

    replacement_token = opaque_token_service.generate_token()
    rotated = rotate_refresh_session(
        session,
        replacement_session_id=uuid4(),
        replacement_token_hash=replacement_token.token_hash,
        replacement_expires_at=now + refresh_token_ttl,
        now=now,
    )
    await refresh_session_repository.save(rotated.revoked_session)
    saved_replacement = await refresh_session_repository.save(rotated.replacement_session)

    access = issue_access_token(
        identity=identity,
        access_token_service=access_token_service,
        now=now,
        access_token_ttl=access_token_ttl,
    )
    return RefreshAuthenticationResult(
        status=RefreshAuthenticationStatus.REFRESHED,
        user=user,
        workspace=identity.workspace,
        membership=identity.membership,
        tokens=IssuedSessionTokens(
            access_token=access.token,
            access_token_expires_at=access.expires_at,
            refresh_token=replacement_token.plaintext,
            refresh_token_expires_at=saved_replacement.expires_at,
            refresh_session=saved_replacement,
        ),
    )


async def logout_current_session(
    *,
    actor: AuthenticatedActor,
    refresh_token: str,
    refresh_session_repository: RefreshSessionRepository,
    audit_log_repository: AuthAuditLogRepository,
    opaque_token_service: OpaqueTokenService,
    now: datetime,
) -> LogoutResult:
    session = await refresh_session_repository.get_by_token_hash_for_update(
        opaque_token_service.hash_token(refresh_token),
    )
    if session is None or session.user_id != actor.user_id:
        return LogoutResult(status=LogoutStatus.LOGGED_OUT, revoked=False)
    if session.revoked_at is not None:
        return LogoutResult(status=LogoutStatus.LOGGED_OUT, revoked=False)

    await refresh_session_repository.save(
        replace(
            session,
            revoked_at=now,
            revoked_reason=RefreshSessionRevocationReason.LOGOUT,
        ),
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.LOGOUT_SUCCEEDED,
            now=now,
            workspace_id=session.workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=actor.user_id,
            event_details={"session_id": str(session.session_id)},
        ),
    )
    return LogoutResult(status=LogoutStatus.LOGGED_OUT, revoked=True)


async def logout_all_sessions(
    *,
    actor: AuthenticatedActor,
    refresh_session_repository: RefreshSessionRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> LogoutResult:
    revoked = await revoke_user_refresh_sessions(
        user_id=actor.user_id,
        refresh_session_repository=refresh_session_repository,
        reason=RefreshSessionRevocationReason.LOGOUT_ALL,
        now=now,
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.LOGOUT_ALL_SUCCEEDED,
            now=now,
            workspace_id=actor.active_workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=actor.user_id,
            event_details={"revoked_session_count": str(len(revoked))},
        ),
    )
    return LogoutResult(status=LogoutStatus.LOGGED_OUT, revoked=bool(revoked))


async def request_password_reset(
    *,
    email: str,
    user_repository: UserRepository,
    credential_repository: PasswordCredentialRepository,
    reset_token_repository: PasswordResetTokenRepository,
    audit_log_repository: AuthAuditLogRepository,
    opaque_token_service: OpaqueTokenService,
    email_provider: EmailProvider,
    now: datetime,
    reset_token_ttl: timedelta = DEFAULT_PASSWORD_RESET_TOKEN_TTL,
) -> ForgotPasswordResult:
    try:
        email_normalized = normalize_email_address(email)
    except ValidationError:
        return ForgotPasswordResult(status=ForgotPasswordStatus.ACCEPTED)

    user = await user_repository.get_by_email_normalized(email_normalized)
    if user is None:
        return ForgotPasswordResult(status=ForgotPasswordStatus.ACCEPTED)

    credential = await credential_repository.get_by_user_id(user.user_id)
    if credential is None:
        return ForgotPasswordResult(status=ForgotPasswordStatus.ACCEPTED)

    reset_token = opaque_token_service.generate_token()
    saved_reset_token = await reset_token_repository.save(
        PasswordResetToken(
            reset_token_id=uuid4(),
            user_id=user.user_id,
            token_hash=reset_token.token_hash,
            expires_at=now + reset_token_ttl,
            used_at=None,
            created_at=now,
        ),
    )
    await email_provider.send(
        EmailMessage(
            to_email=user.email,
            subject="Reset your password",
            body=_password_reset_email_body(reset_token.plaintext),
            idempotency_key=f"auth-reset:{saved_reset_token.reset_token_id}:{saved_reset_token.expires_at.isoformat()}",
        ),
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.PASSWORD_RESET_REQUESTED,
            now=now,
            subject_user_id=user.user_id,
            event_details={"reset_token_id": str(saved_reset_token.reset_token_id)},
        ),
    )
    return ForgotPasswordResult(status=ForgotPasswordStatus.ACCEPTED)


async def reset_password(
    *,
    reset_token: str,
    new_password: str,
    user_repository: UserRepository,
    credential_repository: PasswordCredentialRepository,
    reset_token_repository: PasswordResetTokenRepository,
    refresh_session_repository: RefreshSessionRepository,
    audit_log_repository: AuthAuditLogRepository,
    password_hasher: PasswordHasher,
    opaque_token_service: OpaqueTokenService,
    now: datetime,
) -> ResetPasswordResult:
    stored_reset_token = await reset_token_repository.get_by_token_hash_for_update(
        opaque_token_service.hash_token(reset_token),
    )
    validation_reason = _validate_reset_token(stored_reset_token, now)
    if validation_reason is not None:
        return ResetPasswordResult(
            status=ResetPasswordStatus.REJECTED,
            reasons=(validation_reason,),
        )
    assert stored_reset_token is not None

    password_decision = evaluate_password_policy(new_password)
    if not password_decision.accepted:
        return ResetPasswordResult(
            status=ResetPasswordStatus.REJECTED,
            reasons=(AuthReasonCode.PASSWORD_POLICY_FAILED,),
            password_policy_reasons=password_decision.reasons,
        )

    user = await user_repository.get_by_id(stored_reset_token.user_id)
    if user is None:
        return ResetPasswordResult(
            status=ResetPasswordStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
        )

    credential = await credential_repository.get_by_user_id_for_update(user.user_id)
    password_hash = password_hasher.hash_password(new_password)
    await credential_repository.save(
        PasswordCredential(
            user_id=user.user_id,
            password_hash=password_hash,
            password_changed_at=now,
            failed_attempt_count=0,
            locked_until=None,
            created_at=credential.created_at if credential is not None else now,
            updated_at=now,
        ),
    )
    if user.status == UserStatus.LOCKED:
        user = await user_repository.save(replace(user, status=UserStatus.ACTIVE, updated_at=now))

    await reset_token_repository.save(replace(stored_reset_token, used_at=now))
    await revoke_user_refresh_sessions(
        user_id=user.user_id,
        refresh_session_repository=refresh_session_repository,
        reason=RefreshSessionRevocationReason.PASSWORD_RESET,
        now=now,
    )
    await audit_log_repository.append(
        _auth_audit_log(
            event_type=AuthAuditEventType.PASSWORD_RESET_COMPLETED,
            now=now,
            subject_user_id=user.user_id,
            event_details={"reset_token_id": str(stored_reset_token.reset_token_id)},
        ),
    )
    return ResetPasswordResult(status=ResetPasswordStatus.RESET, user=user)


async def get_current_user(
    *,
    actor: AuthenticatedActor,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> CurrentUserResult:
    user = await user_repository.get_by_id(actor.user_id)
    if user is None:
        return CurrentUserResult(
            status=CurrentUserStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
        )

    workspace = None
    membership = None
    if actor.active_workspace_id is not None:
        workspace = await workspace_repository.get_by_id(actor.active_workspace_id)
    if actor.active_membership_id is not None:
        membership = await membership_repository.get_by_id(actor.active_membership_id)

    return CurrentUserResult(
        status=CurrentUserStatus.FOUND,
        user=user,
        workspace=workspace,
        membership=membership,
        permissions=allowed_permissions(actor),
    )


async def switch_active_workspace(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    access_token_service: AccessTokenService,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
) -> SwitchWorkspaceResult:
    user = await user_repository.get_by_id(actor.user_id)
    if user is None:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_FOUND,),
        )
    if user.status != UserStatus.ACTIVE:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.USER_NOT_ACTIVE,),
        )

    membership = await membership_repository.get_by_user_and_workspace(actor.user_id, workspace_id)
    if membership is None:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )
    if workspace.status != WorkspaceStatus.ACTIVE:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_ACTIVE,),
        )
    if membership.status != WorkspaceMembershipStatus.ACTIVE:
        return SwitchWorkspaceResult(
            status=SwitchWorkspaceStatus.REJECTED,
            reasons=(AuthReasonCode.MEMBERSHIP_NOT_ACTIVE,),
        )

    identity = AuthIdentityContext(user=user, workspace=workspace, membership=membership)
    issued_access = issue_access_token(
        identity=identity,
        access_token_service=access_token_service,
        now=now,
        access_token_ttl=access_token_ttl,
    )
    return SwitchWorkspaceResult(
        status=SwitchWorkspaceStatus.SWITCHED,
        user=user,
        workspace=workspace,
        membership=membership,
        access_token=issued_access.token,
        access_token_expires_at=issued_access.expires_at,
    )


async def _resolve_signin_identity(
    *,
    user: User,
    requested_workspace_id: UUID | None,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> tuple[AuthIdentityContext | None, AuthReasonCode]:
    contexts = await list_identity_contexts_for_user(
        user=user,
        membership_repository=membership_repository,
        workspace_repository=workspace_repository,
    )
    active_contexts = tuple(
        context for context in contexts if is_active_workspace_membership_context(context)
    )
    if requested_workspace_id is not None:
        for context in contexts:
            if context.workspace.workspace_id != requested_workspace_id:
                continue
            if context.workspace.status != WorkspaceStatus.ACTIVE:
                return None, AuthReasonCode.WORKSPACE_NOT_ACTIVE
            if context.membership.status != WorkspaceMembershipStatus.ACTIVE:
                return None, AuthReasonCode.MEMBERSHIP_NOT_ACTIVE
            return context, AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND
        return None, AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND
    if not active_contexts:
        return None, AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND
    if len(active_contexts) > 1:
        return None, AuthReasonCode.WORKSPACE_SELECTION_REQUIRED
    return active_contexts[0], AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND


def _validate_invitation(invitation: UserInvitation | None, now: datetime) -> AuthReasonCode | None:
    if invitation is None:
        return AuthReasonCode.INVITATION_NOT_FOUND
    if invitation.revoked_at is not None:
        return AuthReasonCode.INVITATION_REVOKED
    if invitation.accepted_at is not None:
        return AuthReasonCode.INVITATION_ALREADY_ACCEPTED
    if invitation.expires_at <= now:
        return AuthReasonCode.INVITATION_EXPIRED
    return None


def _validate_reset_token(
    reset_token: PasswordResetToken | None,
    now: datetime,
) -> AuthReasonCode | None:
    if reset_token is None:
        return AuthReasonCode.RESET_TOKEN_NOT_FOUND
    if reset_token.used_at is not None:
        return AuthReasonCode.RESET_TOKEN_ALREADY_USED
    if reset_token.expires_at <= now:
        return AuthReasonCode.RESET_TOKEN_EXPIRED
    return None


def _clear_expired_lock(
    *,
    user: User,
    credential: PasswordCredential,
    now: datetime,
) -> tuple[User, PasswordCredential, bool]:
    if credential.locked_until is None or credential.locked_until > now:
        return user, credential, False
    normalized_user = user
    if user.status == UserStatus.LOCKED:
        normalized_user = replace(user, status=UserStatus.ACTIVE, updated_at=now)
    normalized_credential = replace(
        credential,
        failed_attempt_count=0,
        locked_until=None,
        updated_at=now,
    )
    return normalized_user, normalized_credential, True


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _password_reset_email_body(reset_token: str) -> str:
    return f"Use this password reset token to reset your password: {reset_token}"


def _auth_audit_log(
    *,
    event_type: AuthAuditEventType,
    now: datetime,
    workspace_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    subject_user_id: UUID | None = None,
    event_details: dict[str, str] | None = None,
) -> AuthAuditLog:
    return AuthAuditLog(
        audit_log_id=uuid4(),
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        event_type=event_type,
        event_details=event_details or {},
        created_at=now,
    )


_INVITABLE_WORKSPACE_ROLES = frozenset(
    {
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        WorkspaceMembershipRole.MANAGER,
        WorkspaceMembershipRole.ASSIGNED_AGENT,
    },
)
