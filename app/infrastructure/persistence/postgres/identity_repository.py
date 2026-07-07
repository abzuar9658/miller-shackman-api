from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import RefreshSessionId, UserId, WorkspaceId, WorkspaceMembershipId
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    PasswordCredential,
    PasswordResetToken,
    RefreshSession,
    RefreshSessionRevocationReason,
    User,
    UserInvitation,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.infrastructure.persistence.postgres.models import (
    AuthAuditLogModel,
    PasswordCredentialModel,
    PasswordResetTokenModel,
    RefreshSessionModel,
    UserInvitationModel,
    UserModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)


class PostgresUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UserId) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.user_id == user_id),
        )
        model = result.scalar_one_or_none()
        return _user_from_model(model) if model else None

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email_normalized == email_normalized),
        )
        model = result.scalar_one_or_none()
        return _user_from_model(model) if model else None

    async def save(self, user: User) -> User:
        statement = (
            insert(UserModel)
            .values(**_user_to_values(user))
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=_user_update_values(user),
            )
            .returning(UserModel)
        )
        result = await self._session.execute(statement)
        return _user_from_model(result.scalar_one())


class PostgresWorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, workspace_id: WorkspaceId) -> Workspace | None:
        result = await self._session.execute(
            select(WorkspaceModel).where(WorkspaceModel.workspace_id == workspace_id),
        )
        model = result.scalar_one_or_none()
        return _workspace_from_model(model) if model else None

    async def save(self, workspace: Workspace) -> Workspace:
        statement = (
            insert(WorkspaceModel)
            .values(**_workspace_to_values(workspace))
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_=_workspace_update_values(workspace),
            )
            .returning(WorkspaceModel)
        )
        result = await self._session.execute(statement)
        return _workspace_from_model(result.scalar_one())


class PostgresWorkspaceMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        membership_id: WorkspaceMembershipId,
    ) -> WorkspaceMembership | None:
        result = await self._session.execute(
            select(WorkspaceMembershipModel).where(
                WorkspaceMembershipModel.membership_id == membership_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _membership_from_model(model) if model else None

    async def get_by_user_and_workspace(
        self,
        user_id: UserId,
        workspace_id: WorkspaceId,
    ) -> WorkspaceMembership | None:
        result = await self._session.execute(
            select(WorkspaceMembershipModel).where(
                WorkspaceMembershipModel.user_id == user_id,
                WorkspaceMembershipModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _membership_from_model(model) if model else None

    async def list_by_user_id(self, user_id: UserId) -> tuple[WorkspaceMembership, ...]:
        result = await self._session.execute(
            select(WorkspaceMembershipModel)
            .where(WorkspaceMembershipModel.user_id == user_id)
            .order_by(WorkspaceMembershipModel.created_at.asc()),
        )
        models = result.scalars().all()
        return _models_to_memberships(models)

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        statement = (
            insert(WorkspaceMembershipModel)
            .values(**_membership_to_values(membership))
            .on_conflict_do_update(
                index_elements=["membership_id"],
                set_=_membership_update_values(membership),
            )
            .returning(WorkspaceMembershipModel)
        )
        result = await self._session.execute(statement)
        return _membership_from_model(result.scalar_one())


class PostgresPasswordCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: UserId) -> PasswordCredential | None:
        result = await self._session.execute(
            _credential_by_user_id_statement(user_id=user_id, for_update=False),
        )
        model = result.scalar_one_or_none()
        return _password_credential_from_model(model) if model else None

    async def get_by_user_id_for_update(self, user_id: UserId) -> PasswordCredential | None:
        result = await self._session.execute(
            _credential_by_user_id_statement(user_id=user_id, for_update=True),
        )
        model = result.scalar_one_or_none()
        return _password_credential_from_model(model) if model else None

    async def save(self, credential: PasswordCredential) -> PasswordCredential:
        statement = (
            insert(PasswordCredentialModel)
            .values(**_password_credential_to_values(credential))
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=_password_credential_update_values(credential),
            )
            .returning(PasswordCredentialModel)
        )
        result = await self._session.execute(statement)
        return _password_credential_from_model(result.scalar_one())


class PostgresRefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, session_id: RefreshSessionId) -> RefreshSession | None:
        result = await self._session.execute(
            select(RefreshSessionModel).where(RefreshSessionModel.session_id == session_id),
        )
        model = result.scalar_one_or_none()
        return _refresh_session_from_model(model) if model else None

    async def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        result = await self._session.execute(
            _refresh_session_by_token_hash_statement(token_hash=token_hash, for_update=False),
        )
        model = result.scalar_one_or_none()
        return _refresh_session_from_model(model) if model else None

    async def get_by_token_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        result = await self._session.execute(
            _refresh_session_by_token_hash_statement(token_hash=token_hash, for_update=True),
        )
        model = result.scalar_one_or_none()
        return _refresh_session_from_model(model) if model else None

    async def list_by_user_id(self, user_id: UserId) -> tuple[RefreshSession, ...]:
        result = await self._session.execute(
            select(RefreshSessionModel)
            .where(RefreshSessionModel.user_id == user_id)
            .order_by(RefreshSessionModel.created_at.asc()),
        )
        models = result.scalars().all()
        return _models_to_refresh_sessions(models)

    async def save(self, session: RefreshSession) -> RefreshSession:
        statement = (
            insert(RefreshSessionModel)
            .values(**_refresh_session_to_values(session))
            .on_conflict_do_update(
                index_elements=["session_id"],
                set_=_refresh_session_update_values(session),
            )
            .returning(RefreshSessionModel)
        )
        result = await self._session.execute(statement)
        return _refresh_session_from_model(result.scalar_one())


class PostgresPasswordResetTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            _password_reset_token_by_hash_statement(token_hash=token_hash, for_update=False),
        )
        model = result.scalar_one_or_none()
        return _password_reset_token_from_model(model) if model else None

    async def get_by_token_hash_for_update(self, token_hash: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            _password_reset_token_by_hash_statement(token_hash=token_hash, for_update=True),
        )
        model = result.scalar_one_or_none()
        return _password_reset_token_from_model(model) if model else None

    async def save(self, token: PasswordResetToken) -> PasswordResetToken:
        statement = (
            insert(PasswordResetTokenModel)
            .values(**_password_reset_token_to_values(token))
            .on_conflict_do_update(
                index_elements=["reset_token_id"],
                set_=_password_reset_token_update_values(token),
            )
            .returning(PasswordResetTokenModel)
        )
        result = await self._session.execute(statement)
        return _password_reset_token_from_model(result.scalar_one())


class PostgresInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> UserInvitation | None:
        result = await self._session.execute(
            _invitation_by_token_hash_statement(token_hash=token_hash, for_update=False),
        )
        model = result.scalar_one_or_none()
        return _invitation_from_model(model) if model else None

    async def get_by_token_hash_for_update(self, token_hash: str) -> UserInvitation | None:
        result = await self._session.execute(
            _invitation_by_token_hash_statement(token_hash=token_hash, for_update=True),
        )
        model = result.scalar_one_or_none()
        return _invitation_from_model(model) if model else None

    async def get_by_workspace_and_email_normalized(
        self,
        workspace_id: WorkspaceId,
        email_normalized: str,
    ) -> UserInvitation | None:
        result = await self._session.execute(
            select(UserInvitationModel).where(
                UserInvitationModel.workspace_id == workspace_id,
                UserInvitationModel.email_normalized == email_normalized,
            ),
        )
        model = result.scalar_one_or_none()
        return _invitation_from_model(model) if model else None

    async def save(self, invitation: UserInvitation) -> UserInvitation:
        statement = (
            insert(UserInvitationModel)
            .values(**_invitation_to_values(invitation))
            .on_conflict_do_update(
                index_elements=["invitation_id"],
                set_=_invitation_update_values(invitation),
            )
            .returning(UserInvitationModel)
        )
        result = await self._session.execute(statement)
        return _invitation_from_model(result.scalar_one())


class PostgresAuthAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, audit_log: AuthAuditLog) -> AuthAuditLog:
        statement = insert(AuthAuditLogModel).values(**_audit_log_to_values(audit_log)).returning(
            AuthAuditLogModel,
        )
        result = await self._session.execute(statement)
        return _audit_log_from_model(result.scalar_one())


def _user_to_values(user: User) -> dict[str, object]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "email_normalized": user.email_normalized,
        "full_name": user.full_name,
        "status": user.status.value,
        "email_verified_at": user.email_verified_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _user_update_values(user: User) -> dict[str, object]:
    values = _user_to_values(user)
    values.pop("user_id")
    return values


def _user_from_model(model: UserModel) -> User:
    return User(
        user_id=model.user_id,
        email=model.email,
        email_normalized=model.email_normalized,
        full_name=model.full_name,
        status=UserStatus(model.status),
        email_verified_at=model.email_verified_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _workspace_to_values(workspace: Workspace) -> dict[str, object]:
    return {
        "workspace_id": workspace.workspace_id,
        "name": workspace.name,
        "status": workspace.status.value,
        "default_timezone": workspace.default_timezone,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def _workspace_update_values(workspace: Workspace) -> dict[str, object]:
    values = _workspace_to_values(workspace)
    values.pop("workspace_id")
    return values


def _workspace_from_model(model: WorkspaceModel) -> Workspace:
    return Workspace(
        workspace_id=model.workspace_id,
        name=model.name,
        status=WorkspaceStatus(model.status),
        default_timezone=model.default_timezone,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _membership_to_values(membership: WorkspaceMembership) -> dict[str, object]:
    return {
        "membership_id": membership.membership_id,
        "workspace_id": membership.workspace_id,
        "user_id": membership.user_id,
        "role": membership.role.value,
        "status": membership.status.value,
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
    }


def _membership_update_values(membership: WorkspaceMembership) -> dict[str, object]:
    values = _membership_to_values(membership)
    values.pop("membership_id")
    return values


def _membership_from_model(model: WorkspaceMembershipModel) -> WorkspaceMembership:
    return WorkspaceMembership(
        membership_id=model.membership_id,
        workspace_id=model.workspace_id,
        user_id=model.user_id,
        role=WorkspaceMembershipRole(model.role),
        status=WorkspaceMembershipStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _password_credential_to_values(credential: PasswordCredential) -> dict[str, object]:
    return {
        "user_id": credential.user_id,
        "password_hash": credential.password_hash,
        "password_changed_at": credential.password_changed_at,
        "failed_attempt_count": credential.failed_attempt_count,
        "locked_until": credential.locked_until,
        "created_at": credential.created_at,
        "updated_at": credential.updated_at,
    }


def _password_credential_update_values(credential: PasswordCredential) -> dict[str, object]:
    values = _password_credential_to_values(credential)
    values.pop("user_id")
    return values


def _password_credential_from_model(model: PasswordCredentialModel) -> PasswordCredential:
    return PasswordCredential(
        user_id=model.user_id,
        password_hash=model.password_hash,
        password_changed_at=model.password_changed_at,
        failed_attempt_count=model.failed_attempt_count,
        locked_until=model.locked_until,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _refresh_session_to_values(session: RefreshSession) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "workspace_id": session.workspace_id,
        "refresh_token_hash": session.refresh_token_hash,
        "family_id": session.family_id,
        "rotated_from_session_id": session.rotated_from_session_id,
        "expires_at": session.expires_at,
        "revoked_at": session.revoked_at,
        "revoked_reason": session.revoked_reason.value if session.revoked_reason else None,
        "created_at": session.created_at,
        "last_used_at": session.last_used_at,
    }


def _refresh_session_update_values(session: RefreshSession) -> dict[str, object]:
    values = _refresh_session_to_values(session)
    values.pop("session_id")
    return values


def _refresh_session_from_model(model: RefreshSessionModel) -> RefreshSession:
    return RefreshSession(
        session_id=model.session_id,
        user_id=model.user_id,
        workspace_id=model.workspace_id,
        refresh_token_hash=model.refresh_token_hash,
        family_id=model.family_id,
        rotated_from_session_id=model.rotated_from_session_id,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        revoked_reason=(
            RefreshSessionRevocationReason(model.revoked_reason)
            if model.revoked_reason is not None
            else None
        ),
        created_at=model.created_at,
        last_used_at=model.last_used_at,
    )


def _password_reset_token_to_values(token: PasswordResetToken) -> dict[str, object]:
    return {
        "reset_token_id": token.reset_token_id,
        "user_id": token.user_id,
        "token_hash": token.token_hash,
        "expires_at": token.expires_at,
        "used_at": token.used_at,
        "created_at": token.created_at,
    }


def _password_reset_token_update_values(token: PasswordResetToken) -> dict[str, object]:
    values = _password_reset_token_to_values(token)
    values.pop("reset_token_id")
    return values


def _password_reset_token_from_model(model: PasswordResetTokenModel) -> PasswordResetToken:
    return PasswordResetToken(
        reset_token_id=model.reset_token_id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        used_at=model.used_at,
        created_at=model.created_at,
    )


def _invitation_to_values(invitation: UserInvitation) -> dict[str, object]:
    return {
        "invitation_id": invitation.invitation_id,
        "workspace_id": invitation.workspace_id,
        "user_id": invitation.user_id,
        "email": invitation.email,
        "email_normalized": invitation.email_normalized,
        "role": invitation.role.value,
        "token_hash": invitation.token_hash,
        "expires_at": invitation.expires_at,
        "accepted_at": invitation.accepted_at,
        "revoked_at": invitation.revoked_at,
        "created_by_user_id": invitation.created_by_user_id,
        "created_at": invitation.created_at,
    }


def _invitation_update_values(invitation: UserInvitation) -> dict[str, object]:
    values = _invitation_to_values(invitation)
    values.pop("invitation_id")
    return values


def _invitation_from_model(model: UserInvitationModel) -> UserInvitation:
    return UserInvitation(
        invitation_id=model.invitation_id,
        workspace_id=model.workspace_id,
        user_id=model.user_id,
        email=model.email,
        email_normalized=model.email_normalized,
        role=WorkspaceMembershipRole(model.role),
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        accepted_at=model.accepted_at,
        revoked_at=model.revoked_at,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
    )


def _audit_log_to_values(audit_log: AuthAuditLog) -> dict[str, object]:
    return {
        "audit_log_id": audit_log.audit_log_id,
        "workspace_id": audit_log.workspace_id,
        "actor_user_id": audit_log.actor_user_id,
        "subject_user_id": audit_log.subject_user_id,
        "event_type": audit_log.event_type.value,
        "event_details": dict(audit_log.event_details),
        "created_at": audit_log.created_at,
    }


def _audit_log_from_model(model: AuthAuditLogModel) -> AuthAuditLog:
    return AuthAuditLog(
        audit_log_id=model.audit_log_id,
        workspace_id=model.workspace_id,
        actor_user_id=model.actor_user_id,
        subject_user_id=model.subject_user_id,
        event_type=AuthAuditEventType(model.event_type),
        event_details=dict(model.event_details),
        created_at=model.created_at,
    )


def _credential_by_user_id_statement(
    *,
    user_id: UserId,
    for_update: bool,
) -> Select[tuple[PasswordCredentialModel]]:
    statement = select(PasswordCredentialModel).where(PasswordCredentialModel.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return statement


def _refresh_session_by_token_hash_statement(
    *,
    token_hash: str,
    for_update: bool,
) -> Select[tuple[RefreshSessionModel]]:
    statement = select(RefreshSessionModel).where(
        RefreshSessionModel.refresh_token_hash == token_hash,
    )
    if for_update:
        statement = statement.with_for_update()
    return statement


def _password_reset_token_by_hash_statement(
    *,
    token_hash: str,
    for_update: bool,
) -> Select[tuple[PasswordResetTokenModel]]:
    statement = select(PasswordResetTokenModel).where(
        PasswordResetTokenModel.token_hash == token_hash,
    )
    if for_update:
        statement = statement.with_for_update()
    return statement


def _invitation_by_token_hash_statement(
    *,
    token_hash: str,
    for_update: bool,
) -> Select[tuple[UserInvitationModel]]:
    statement = select(UserInvitationModel).where(UserInvitationModel.token_hash == token_hash)
    if for_update:
        statement = statement.with_for_update()
    return statement


def _models_to_memberships(
    models: Sequence[WorkspaceMembershipModel],
) -> tuple[WorkspaceMembership, ...]:
    return tuple(_membership_from_model(model) for model in models)


def _models_to_refresh_sessions(
    models: Sequence[RefreshSessionModel],
) -> tuple[RefreshSession, ...]:
    return tuple(_refresh_session_from_model(model) for model in models)