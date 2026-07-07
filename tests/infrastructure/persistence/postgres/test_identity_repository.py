from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    PasswordCredential,
    PasswordResetToken,
    RefreshSession,
    User,
    UserInvitation,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresInvitationRepository,
    PostgresPasswordCredentialRepository,
    PostgresPasswordResetTokenRepository,
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.persistence.postgres.models import (
    AuthAuditLogModel,
    PasswordCredentialModel,
    PasswordResetTokenModel,
    RefreshSessionModel,
    UserInvitationModel,
    UserModel,
    WorkspaceMembershipModel,
)

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
USER_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000003")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000004")
FAMILY_ID = UUID("00000000-0000-0000-0000-000000000005")
RESET_TOKEN_ID = UUID("00000000-0000-0000-0000-000000000006")
INVITATION_ID = UUID("00000000-0000-0000-0000-000000000007")
AUDIT_LOG_ID = UUID("00000000-0000-0000-0000-000000000008")
CREATOR_USER_ID = UUID("00000000-0000-0000-0000-000000000009")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def test_user_repository_get_by_email_normalized_maps_domain_user() -> None:
    model = UserModel(
        user_id=USER_ID,
        email="Agent@example.com",
        email_normalized="agent@example.com",
        full_name="Agent Smith",
        status=UserStatus.ACTIVE.value,
        email_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    result = _run(
        PostgresUserRepository(cast(AsyncSession, session)).get_by_email_normalized(
            "agent@example.com",
        ),
    )

    assert result == User(
        user_id=USER_ID,
        email="Agent@example.com",
        email_normalized="agent@example.com",
        full_name="Agent Smith",
        status=UserStatus.ACTIVE,
        email_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    assert "users.email_normalized" in str(session.statements[0])


def test_workspace_membership_repository_lists_user_memberships() -> None:
    first = WorkspaceMembershipModel(
        membership_id=MEMBERSHIP_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT.value,
        status=WorkspaceMembershipStatus.ACTIVE.value,
        created_at=NOW,
        updated_at=NOW,
    )
    second = WorkspaceMembershipModel(
        membership_id=UUID("00000000-0000-0000-0000-00000000000a"),
        workspace_id=UUID("00000000-0000-0000-0000-00000000000b"),
        user_id=USER_ID,
        role=WorkspaceMembershipRole.MANAGER.value,
        status=WorkspaceMembershipStatus.INVITED.value,
        created_at=NOW + timedelta(minutes=1),
        updated_at=NOW + timedelta(minutes=1),
    )
    session = _FakeSession(_FakeResult(scalar_values=[first, second]))

    memberships = _run(
        PostgresWorkspaceMembershipRepository(cast(AsyncSession, session)).list_by_user_id(
            USER_ID,
        ),
    )

    assert len(memberships) == 2
    assert memberships[0].role == WorkspaceMembershipRole.ASSIGNED_AGENT
    assert memberships[1].role == WorkspaceMembershipRole.MANAGER
    assert memberships[1].status == WorkspaceMembershipStatus.INVITED


def test_password_credential_repository_get_by_user_id_for_update_uses_locking() -> None:
    model = PasswordCredentialModel(
        user_id=USER_ID,
        password_hash="hashed",
        password_changed_at=NOW,
        failed_attempt_count=2,
        locked_until=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    credential = _run(
        PostgresPasswordCredentialRepository(cast(AsyncSession, session)).get_by_user_id_for_update(
            USER_ID,
        ),
    )

    assert credential == PasswordCredential(
        user_id=USER_ID,
        password_hash="hashed",
        password_changed_at=NOW,
        failed_attempt_count=2,
        locked_until=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    assert cast(Any, session.statements[0])._for_update_arg is not None


def test_refresh_session_repository_save_returns_domain_session() -> None:
    domain_session = RefreshSession(
        session_id=SESSION_ID,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        refresh_token_hash="hashed-token",
        family_id=FAMILY_ID,
        rotated_from_session_id=None,
        expires_at=NOW + timedelta(days=30),
        revoked_at=None,
        revoked_reason=None,
        created_at=NOW,
        last_used_at=None,
    )
    model = RefreshSessionModel(
        session_id=SESSION_ID,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        refresh_token_hash="hashed-token",
        family_id=FAMILY_ID,
        rotated_from_session_id=None,
        expires_at=NOW + timedelta(days=30),
        revoked_at=None,
        revoked_reason=None,
        created_at=NOW,
        last_used_at=None,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    saved = _run(PostgresRefreshSessionRepository(cast(AsyncSession, session)).save(domain_session))

    assert saved == domain_session


def test_password_reset_token_repository_get_by_token_hash_for_update_uses_locking() -> None:
    model = PasswordResetTokenModel(
        reset_token_id=RESET_TOKEN_ID,
        user_id=USER_ID,
        token_hash="reset-hash",
        expires_at=NOW + timedelta(minutes=30),
        used_at=None,
        created_at=NOW,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    token = _run(
        PostgresPasswordResetTokenRepository(
            cast(AsyncSession, session),
        ).get_by_token_hash_for_update("reset-hash"),
    )

    assert token == PasswordResetToken(
        reset_token_id=RESET_TOKEN_ID,
        user_id=USER_ID,
        token_hash="reset-hash",
        expires_at=NOW + timedelta(minutes=30),
        used_at=None,
        created_at=NOW,
    )
    assert cast(Any, session.statements[0])._for_update_arg is not None


def test_invitation_repository_get_by_workspace_and_email_normalized_maps_role() -> None:
    model = UserInvitationModel(
        invitation_id=INVITATION_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN.value,
        token_hash="invite-hash",
        expires_at=NOW + timedelta(days=7),
        accepted_at=None,
        revoked_at=None,
        created_by_user_id=CREATOR_USER_ID,
        created_at=NOW,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    invitation = _run(
        PostgresInvitationRepository(
            cast(AsyncSession, session),
        ).get_by_workspace_and_email_normalized(WORKSPACE_ID, "agent@example.com"),
    )

    assert invitation == UserInvitation(
        invitation_id=INVITATION_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        token_hash="invite-hash",
        expires_at=NOW + timedelta(days=7),
        accepted_at=None,
        revoked_at=None,
        created_by_user_id=CREATOR_USER_ID,
        created_at=NOW,
    )
    assert "user_invitations.workspace_id" in str(session.statements[0])


def test_auth_audit_log_repository_append_returns_saved_log() -> None:
    audit_log = AuthAuditLog(
        audit_log_id=AUDIT_LOG_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id=CREATOR_USER_ID,
        subject_user_id=USER_ID,
        event_type=AuthAuditEventType.USER_INVITED,
        event_details={"role": "brokerage_admin"},
        created_at=NOW,
    )
    model = AuthAuditLogModel(
        audit_log_id=AUDIT_LOG_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id=CREATOR_USER_ID,
        subject_user_id=USER_ID,
        event_type=AuthAuditEventType.USER_INVITED.value,
        event_details={"role": "brokerage_admin"},
        created_at=NOW,
    )
    session = _FakeSession(_FakeResult(scalar_value=model))

    saved = _run(PostgresAuthAuditLogRepository(cast(AsyncSession, session)).append(audit_log))

    assert saved == audit_log


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)