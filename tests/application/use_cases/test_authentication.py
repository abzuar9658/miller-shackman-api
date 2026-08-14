from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID

from app.application.ports.auth import (
    AccessTokenSubject,
    DecodedAccessToken,
    IssuedAccessToken,
    OpaqueToken,
)
from app.application.ports.messaging import EmailMessage
from app.application.use_cases.authentication import (
    AuthReasonCode,
    CompleteInvitedSignupStatus,
    CurrentUserStatus,
    ForgotPasswordStatus,
    InviteWorkspaceUserStatus,
    PreviewInvitationStatus,
    RefreshAuthenticationStatus,
    ResetPasswordStatus,
    SignInStatus,
    SwitchWorkspaceStatus,
    complete_invited_signup,
    get_current_user,
    invite_workspace_user,
    logout_all_sessions,
    logout_current_session,
    preview_invitation,
    refresh_authentication,
    request_password_reset,
    reset_password,
    sign_in,
    switch_active_workspace,
)
from app.domain.compliance import WorkspaceContactPolicy
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.crm_sync import WorkspaceCRMSyncConfig, WorkspaceCRMSyncScheduleTarget
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    AuthenticatedActor,
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
from app.domain.llm import WorkspaceLLMConfig
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig
from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    WorkspaceOperationalControl,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)

T = TypeVar("T")

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
SECOND_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000004")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000005")
SECOND_MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000007")
SECOND_SESSION_ID = UUID("00000000-0000-0000-0000-000000000008")
FAMILY_ID = UUID("00000000-0000-0000-0000-000000000009")
INVITATION_ID = UUID("00000000-0000-0000-0000-00000000000a")
RESET_TOKEN_ID = UUID("00000000-0000-0000-0000-00000000000b")


def test_invite_workspace_user_creates_records_and_sends_email() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    actor = _actor()

    result = _run(
        invite_workspace_user(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            email="agent@example.com",
            role=WorkspaceMembershipRole.ASSIGNED_AGENT,
            full_name="Agent Smith",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            opaque_token_service=deps.opaque_token_service,
            email_provider=deps.email_provider,
            frontend_app_base_url="https://app.millerschackman.test",
            now=NOW,
        ),
    )

    assert result.status == InviteWorkspaceUserStatus.INVITED
    assert result.user is not None
    assert result.user.status == UserStatus.PENDING_VERIFICATION
    assert result.membership is not None
    assert result.membership.status == WorkspaceMembershipStatus.INVITED
    assert result.invitation is not None
    assert result.invitation.token_hash == "hash::invite-token"
    assert len(deps.email_provider.messages) == 1
    assert "https://app.millerschackman.test/signup/invited?token=invite-token" in (
        deps.email_provider.messages[0].body
    )
    assert "invite-token" in deps.email_provider.messages[0].body
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.USER_INVITED


def test_preview_invitation_returns_invitation_and_workspace() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    result = _run(
        preview_invitation(
            invitation_token="invite-token",
            invitation_repository=deps.invitation_repository,
            workspace_repository=deps.workspace_repository,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == PreviewInvitationStatus.VALID
    assert result.invitation is not None
    assert result.invitation.email == "user@example.com"
    assert result.workspace is not None
    assert result.workspace.name == f"Workspace {WORKSPACE_ID}"


def test_preview_invitation_rejects_unknown_token() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()

    result = _run(
        preview_invitation(
            invitation_token="unknown-token",
            invitation_repository=deps.invitation_repository,
            workspace_repository=deps.workspace_repository,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == PreviewInvitationStatus.REJECTED
    assert result.reasons == (AuthReasonCode.INVITATION_NOT_FOUND,)


def test_preview_invitation_rejects_expired_invitation() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    result = _run(
        preview_invitation(
            invitation_token="invite-token",
            invitation_repository=deps.invitation_repository,
            workspace_repository=deps.workspace_repository,
            opaque_token_service=deps.opaque_token_service,
            now=NOW + timedelta(days=8),
        ),
    )

    assert result.status == PreviewInvitationStatus.REJECTED
    assert result.reasons == (AuthReasonCode.INVITATION_EXPIRED,)


def test_preview_invitation_rejects_inactive_workspace() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace(status=WorkspaceStatus.SUSPENDED)
    deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    result = _run(
        preview_invitation(
            invitation_token="invite-token",
            invitation_repository=deps.invitation_repository,
            workspace_repository=deps.workspace_repository,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == PreviewInvitationStatus.REJECTED
    assert result.reasons == (AuthReasonCode.WORKSPACE_NOT_ACTIVE,)


def test_complete_invited_signup_activates_user_and_issues_tokens() -> None:
    deps = _Dependencies(tokens=["refresh-token"])
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    deps.memberships[MEMBERSHIP_ID] = _membership(status=WorkspaceMembershipStatus.INVITED)
    deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    result = _run(
        complete_invited_signup(
            invitation_token="invite-token",
            full_name="Agent Smith",
            password="strong-password",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            credential_repository=deps.credential_repository,
            invitation_repository=deps.invitation_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == CompleteInvitedSignupStatus.COMPLETED
    assert result.user is not None
    assert result.user.status == UserStatus.ACTIVE
    assert result.membership is not None
    assert result.membership.status == WorkspaceMembershipStatus.ACTIVE
    assert result.tokens is not None
    assert result.tokens.refresh_token == "refresh-token"
    assert deps.credentials[USER_ID].password_hash == "hashed::strong-password"
    assert deps.invitations[INVITATION_ID].accepted_at == NOW


def test_complete_invited_signup_preserves_current_membership_role() -> None:
    deps = _Dependencies(tokens=["refresh-token"])
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    deps.memberships[MEMBERSHIP_ID] = _membership(
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        status=WorkspaceMembershipStatus.INVITED,
    )
    deps.invitations[INVITATION_ID] = _invitation(
        token_hash="hash::invite-token",
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )

    result = _run(
        complete_invited_signup(
            invitation_token="invite-token",
            full_name="Agent Smith",
            password="strong-password",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            credential_repository=deps.credential_repository,
            invitation_repository=deps.invitation_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == CompleteInvitedSignupStatus.COMPLETED
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.BROKERAGE_ADMIN


def test_sign_in_requires_workspace_selection_for_multi_workspace_user() -> None:
    deps = _Dependencies(tokens=["refresh-token"])
    deps.users[USER_ID] = _user()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.workspaces[SECOND_WORKSPACE_ID] = _workspace(workspace_id=SECOND_WORKSPACE_ID)
    deps.memberships[MEMBERSHIP_ID] = _membership()
    deps.memberships[SECOND_MEMBERSHIP_ID] = _membership(
        membership_id=SECOND_MEMBERSHIP_ID,
        workspace_id=SECOND_WORKSPACE_ID,
    )
    deps.credentials[USER_ID] = _credential(password_hash="hashed::correct-password")

    result = _run(
        sign_in(
            email="user@example.com",
            password="correct-password",
            workspace_id=None,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            credential_repository=deps.credential_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == SignInStatus.REJECTED
    assert result.reasons == (AuthReasonCode.WORKSPACE_SELECTION_REQUIRED,)


def test_sign_in_locks_user_after_max_failed_attempts() -> None:
    deps = _Dependencies(tokens=["refresh-token"])
    deps.users[USER_ID] = _user()
    deps.credentials[USER_ID] = _credential(
        password_hash="hashed::correct-password",
        failed_attempt_count=4,
    )

    result = _run(
        sign_in(
            email="user@example.com",
            password="wrong-password",
            workspace_id=WORKSPACE_ID,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            credential_repository=deps.credential_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == SignInStatus.REJECTED
    assert result.reasons == (AuthReasonCode.INVALID_CREDENTIALS,)
    assert deps.credentials[USER_ID].locked_until == NOW + timedelta(minutes=15)
    assert deps.users[USER_ID].status == UserStatus.LOCKED


def test_sign_in_success_resets_failed_attempts_and_issues_tokens() -> None:
    deps = _Dependencies(tokens=["refresh-token"])
    deps.users[USER_ID] = _user()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership()
    deps.credentials[USER_ID] = _credential(
        password_hash="hashed::correct-password",
        failed_attempt_count=2,
    )

    result = _run(
        sign_in(
            email="user@example.com",
            password="correct-password",
            workspace_id=WORKSPACE_ID,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            credential_repository=deps.credential_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == SignInStatus.AUTHENTICATED
    assert result.tokens is not None
    assert result.tokens.refresh_token == "refresh-token"
    assert deps.credentials[USER_ID].failed_attempt_count == 0
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.SIGNIN_SUCCEEDED


def test_refresh_authentication_rotates_refresh_session() -> None:
    deps = _Dependencies(tokens=["refresh-token-next"])
    deps.users[USER_ID] = _user()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership()
    deps.refresh_sessions[SESSION_ID] = _refresh_session(token_hash="hash::refresh-token")

    result = _run(
        refresh_authentication(
            refresh_token="refresh-token",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            refresh_session_repository=deps.refresh_session_repository,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == RefreshAuthenticationStatus.REFRESHED
    assert result.tokens is not None
    assert result.tokens.refresh_token == "refresh-token-next"
    assert (
        deps.refresh_sessions[SESSION_ID].revoked_reason == RefreshSessionRevocationReason.ROTATED
    )
    rotated_session = next(
        session for session_id, session in deps.refresh_sessions.items() if session_id != SESSION_ID
    )
    assert rotated_session.rotated_from_session_id == SESSION_ID


def test_refresh_authentication_detects_reuse_and_revokes_family() -> None:
    deps = _Dependencies(tokens=["unused-token"])
    deps.users[USER_ID] = _user()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership()
    deps.refresh_sessions[SESSION_ID] = _refresh_session(
        token_hash="hash::refresh-token",
        revoked_at=NOW - timedelta(minutes=1),
        revoked_reason=RefreshSessionRevocationReason.ROTATED,
    )
    deps.refresh_sessions[SECOND_SESSION_ID] = _refresh_session(
        session_id=SECOND_SESSION_ID,
        token_hash="hash::refresh-token-active",
    )

    result = _run(
        refresh_authentication(
            refresh_token="refresh-token",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            refresh_session_repository=deps.refresh_session_repository,
            access_token_service=deps.access_token_service,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == RefreshAuthenticationStatus.REJECTED
    assert result.reasons == (AuthReasonCode.REFRESH_TOKEN_REUSE_DETECTED,)
    assert (
        deps.refresh_sessions[SECOND_SESSION_ID].revoked_reason
        == RefreshSessionRevocationReason.REUSE_DETECTED
    )


def test_logout_current_session_revokes_matching_session() -> None:
    deps = _Dependencies()
    deps.refresh_sessions[SESSION_ID] = _refresh_session(token_hash="hash::refresh-token")

    result = _run(
        logout_current_session(
            actor=_actor(user_id=USER_ID),
            refresh_token="refresh-token",
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.revoked is True
    assert deps.refresh_sessions[SESSION_ID].revoked_reason == RefreshSessionRevocationReason.LOGOUT


def test_logout_all_sessions_revokes_all_active_user_sessions() -> None:
    deps = _Dependencies()
    deps.refresh_sessions[SESSION_ID] = _refresh_session()
    deps.refresh_sessions[SECOND_SESSION_ID] = _refresh_session(session_id=SECOND_SESSION_ID)

    result = _run(
        logout_all_sessions(
            actor=_actor(user_id=USER_ID),
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.revoked is True
    assert (
        deps.refresh_sessions[SESSION_ID].revoked_reason
        == RefreshSessionRevocationReason.LOGOUT_ALL
    )
    assert (
        deps.refresh_sessions[SECOND_SESSION_ID].revoked_reason
        == RefreshSessionRevocationReason.LOGOUT_ALL
    )


def test_request_password_reset_is_generic_for_unknown_email() -> None:
    deps = _Dependencies()

    result = _run(
        request_password_reset(
            email="missing@example.com",
            user_repository=deps.user_repository,
            credential_repository=deps.credential_repository,
            reset_token_repository=deps.reset_token_repository,
            audit_log_repository=deps.audit_log_repository,
            opaque_token_service=deps.opaque_token_service,
            email_provider=deps.email_provider,
            now=NOW,
        ),
    )

    assert result.status == ForgotPasswordStatus.ACCEPTED
    assert not deps.email_provider.messages


def test_reset_password_marks_token_used_and_revokes_sessions() -> None:
    deps = _Dependencies()
    deps.users[USER_ID] = _user(status=UserStatus.LOCKED)
    deps.credentials[USER_ID] = _credential(password_hash="hashed::old-password")
    deps.reset_tokens[RESET_TOKEN_ID] = _reset_token(token_hash="hash::reset-token")
    deps.refresh_sessions[SESSION_ID] = _refresh_session()

    result = _run(
        reset_password(
            reset_token="reset-token",
            new_password="new-strong-password",
            user_repository=deps.user_repository,
            credential_repository=deps.credential_repository,
            reset_token_repository=deps.reset_token_repository,
            refresh_session_repository=deps.refresh_session_repository,
            audit_log_repository=deps.audit_log_repository,
            password_hasher=deps.password_hasher,
            opaque_token_service=deps.opaque_token_service,
            now=NOW,
        ),
    )

    assert result.status == ResetPasswordStatus.RESET
    assert deps.reset_tokens[RESET_TOKEN_ID].used_at == NOW
    assert (
        deps.refresh_sessions[SESSION_ID].revoked_reason
        == RefreshSessionRevocationReason.PASSWORD_RESET
    )
    assert deps.users[USER_ID].status == UserStatus.ACTIVE


def test_get_current_user_returns_context_and_permissions() -> None:
    deps = _Dependencies()
    deps.users[USER_ID] = _user()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        get_current_user(
            actor=_actor(
                user_id=USER_ID,
                role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
            ),
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
        ),
    )

    assert result.status == CurrentUserStatus.FOUND
    assert result.workspace is not None
    assert result.membership is not None
    assert "invite_workspace_user" in result.permissions
    assert "edit_paused_search_profile_any_lead" in result.permissions


def test_switch_active_workspace_issues_new_access_token() -> None:
    deps = _Dependencies()
    deps.users[USER_ID] = _user()
    deps.workspaces[SECOND_WORKSPACE_ID] = _workspace(workspace_id=SECOND_WORKSPACE_ID)
    deps.memberships[SECOND_MEMBERSHIP_ID] = _membership(
        membership_id=SECOND_MEMBERSHIP_ID,
        workspace_id=SECOND_WORKSPACE_ID,
    )

    result = _run(
        switch_active_workspace(
            actor=_actor(user_id=USER_ID),
            workspace_id=SECOND_WORKSPACE_ID,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            access_token_service=deps.access_token_service,
            now=NOW,
        ),
    )

    assert result.status == SwitchWorkspaceStatus.SWITCHED
    assert result.access_token is not None
    assert result.workspace is not None
    assert result.workspace.workspace_id == SECOND_WORKSPACE_ID


class _Dependencies:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.users: dict[UUID, User] = {}
        self.workspaces: dict[UUID, Workspace] = {}
        self.memberships: dict[UUID, WorkspaceMembership] = {}
        self.workspace_contact_policies: dict[UUID, WorkspaceContactPolicy] = {}
        self.workspace_crm_sync_configs: dict[UUID, WorkspaceCRMSyncConfig] = {}
        self.workspace_llm_configs: dict[UUID, WorkspaceLLMConfig] = {}
        self.workspace_outbound_drafting_configs: dict[UUID, WorkspaceOutboundDraftingConfig] = {}
        self.workspace_operational_controls: dict[UUID, WorkspaceOperationalControl] = {}
        self.workspace_handoff_configs: dict[UUID, WorkspaceHandoffConfig] = {}
        self.credentials: dict[UUID, PasswordCredential] = {}
        self.refresh_sessions: dict[UUID, RefreshSession] = {}
        self.reset_tokens: dict[UUID, PasswordResetToken] = {}
        self.invitations: dict[UUID, UserInvitation] = {}
        self.user_repository = _FakeUserRepository(self.users)
        self.workspace_repository = _FakeWorkspaceRepository(self.workspaces)
        self.membership_repository = _FakeWorkspaceMembershipRepository(self.memberships)
        self.workspace_contact_policy_repository = _FakeWorkspaceContactPolicyRepository(
            self.workspace_contact_policies,
        )
        self.workspace_crm_sync_config_repository = _FakeWorkspaceCRMSyncConfigRepository(
            self.workspace_crm_sync_configs,
        )
        self.workspace_llm_config_repository = _FakeWorkspaceLLMConfigRepository(
            self.workspace_llm_configs,
        )
        self.workspace_outbound_drafting_config_repository = (
            _FakeWorkspaceOutboundDraftingConfigRepository(
                self.workspace_outbound_drafting_configs,
            )
        )
        self.workspace_operational_control_repository = _FakeWorkspaceOperationalControlRepository(
            self.workspace_operational_controls,
        )
        self.workspace_handoff_config_repository = _FakeWorkspaceHandoffConfigRepository(
            self.workspace_handoff_configs,
        )
        self.credential_repository = _FakePasswordCredentialRepository(self.credentials)
        self.refresh_session_repository = _FakeRefreshSessionRepository(self.refresh_sessions)
        self.reset_token_repository = _FakePasswordResetTokenRepository(self.reset_tokens)
        self.invitation_repository = _FakeInvitationRepository(self.invitations)
        self.audit_log_repository = _FakeAuthAuditLogRepository()
        self.lead_workflow_repository = FakeLeadWorkflowRepository()
        self.workflow_transition_repository = FakeWorkflowTransitionRepository()
        self.temporal_signal_outbox_repository = FakeTemporalSignalOutboxRepository()
        self.email_provider = _FakeEmailProvider()
        self.password_hasher = _FakePasswordHasher()
        self.opaque_token_service = _FakeOpaqueTokenService(
            tokens or ["invite-token", "refresh-token"],
        )
        self.access_token_service = _FakeAccessTokenService()


class _FakeUserRepository:
    def __init__(self, users: dict[UUID, User]) -> None:
        self._users = users

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        return next(
            (user for user in self._users.values() if user.email_normalized == email_normalized),
            None,
        )

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
        return next(
            (user for user in self._users.values() if user.email_normalized == email_normalized),
            None,
        )

    async def save(self, user: User) -> User:
        self._users[user.user_id] = user
        return user


class _FakeWorkspaceRepository:
    def __init__(self, workspaces: dict[UUID, Workspace]) -> None:
        self._workspaces = workspaces

    async def get_by_id(self, workspace_id: UUID) -> Workspace | None:
        return self._workspaces.get(workspace_id)

    async def save(self, workspace: Workspace) -> Workspace:
        self._workspaces[workspace.workspace_id] = workspace
        return workspace


class _FakeWorkspaceMembershipRepository:
    def __init__(self, memberships: dict[UUID, WorkspaceMembership]) -> None:
        self._memberships = memberships

    async def get_by_id(self, membership_id: UUID) -> WorkspaceMembership | None:
        return self._memberships.get(membership_id)

    async def get_by_user_and_workspace(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None:
        return next(
            (
                membership
                for membership in self._memberships.values()
                if membership.user_id == user_id and membership.workspace_id == workspace_id
            ),
            None,
        )

    async def list_by_user_id(self, user_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            membership for membership in self._memberships.values() if membership.user_id == user_id
        )

    async def list_by_workspace_id(
        self,
        workspace_id: UUID,
    ) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            membership
            for membership in self._memberships.values()
            if membership.workspace_id == workspace_id
        )

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        self._memberships[membership.membership_id] = membership
        return membership


class _FakeWorkspaceContactPolicyRepository:
    def __init__(self, policies: dict[UUID, WorkspaceContactPolicy]) -> None:
        self._policies = policies

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceContactPolicy | None:
        return self._policies.get(workspace_id)

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        self._policies[policy.workspace_id] = policy
        return policy


class _FakeWorkspaceHandoffConfigRepository:
    def __init__(self, configs: dict[UUID, WorkspaceHandoffConfig]) -> None:
        self._configs = configs

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceHandoffConfig | None:
        return self._configs.get(workspace_id)

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        self._configs[config.workspace_id] = config
        return config


class _FakeWorkspaceCRMSyncConfigRepository:
    def __init__(self, configs: dict[UUID, WorkspaceCRMSyncConfig]) -> None:
        self._configs = configs

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceCRMSyncConfig | None:
        return self._configs.get(workspace_id)

    async def list_active_workspace_schedule_targets(
        self,
        *,
        limit: int = 100,
        default_interval_seconds: int,
    ) -> tuple[WorkspaceCRMSyncScheduleTarget, ...]:
        targets = [
            WorkspaceCRMSyncScheduleTarget(
                workspace_id=workspace_id,
                crm_sync_enabled=config.crm_sync_enabled,
                crm_sync_interval_seconds=config.crm_sync_interval_seconds,
                automation_status=WorkspaceAutomationStatus.ACTIVE,
            )
            for workspace_id, config in self._configs.items()
        ]
        return tuple(targets[:limit])

    async def save(self, config: WorkspaceCRMSyncConfig) -> WorkspaceCRMSyncConfig:
        self._configs[config.workspace_id] = config
        return config


class _FakeWorkspaceLLMConfigRepository:
    def __init__(self, configs: dict[UUID, WorkspaceLLMConfig]) -> None:
        self._configs = configs

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceLLMConfig | None:
        return self._configs.get(workspace_id)

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        self._configs[config.workspace_id] = config
        return config


class _FakeWorkspaceOutboundDraftingConfigRepository:
    def __init__(self, configs: dict[UUID, WorkspaceOutboundDraftingConfig]) -> None:
        self._configs = configs

    async def get_by_workspace_id(
        self,
        workspace_id: UUID,
    ) -> WorkspaceOutboundDraftingConfig | None:
        return self._configs.get(workspace_id)

    async def save(
        self,
        config: WorkspaceOutboundDraftingConfig,
    ) -> WorkspaceOutboundDraftingConfig:
        self._configs[config.workspace_id] = config
        return config


class _FakeWorkspaceOperationalControlRepository:
    def __init__(self, controls: dict[UUID, WorkspaceOperationalControl]) -> None:
        self._controls = controls

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceOperationalControl | None:
        return self._controls.get(workspace_id)

    async def save(
        self,
        control: WorkspaceOperationalControl,
    ) -> WorkspaceOperationalControl:
        self._controls[control.workspace_id] = control
        return control


class _FakePasswordCredentialRepository:
    def __init__(self, credentials: dict[UUID, PasswordCredential]) -> None:
        self._credentials = credentials

    async def get_by_user_id(self, user_id: UUID) -> PasswordCredential | None:
        return self._credentials.get(user_id)

    async def get_by_user_id_for_update(self, user_id: UUID) -> PasswordCredential | None:
        return self._credentials.get(user_id)

    async def save(self, credential: PasswordCredential) -> PasswordCredential:
        self._credentials[credential.user_id] = credential
        return credential


class _FakeRefreshSessionRepository:
    def __init__(self, sessions: dict[UUID, RefreshSession]) -> None:
        self._sessions = sessions

    async def get_by_id(self, session_id: UUID) -> RefreshSession | None:
        return self._sessions.get(session_id)

    async def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        return next(
            (
                session
                for session in self._sessions.values()
                if session.refresh_token_hash == token_hash
            ),
            None,
        )

    async def get_by_token_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        return await self.get_by_token_hash(token_hash)

    async def list_by_user_id(self, user_id: UUID) -> tuple[RefreshSession, ...]:
        return tuple(session for session in self._sessions.values() if session.user_id == user_id)

    async def save(self, session: RefreshSession) -> RefreshSession:
        self._sessions[session.session_id] = session
        return session


class _FakePasswordResetTokenRepository:
    def __init__(self, tokens: dict[UUID, PasswordResetToken]) -> None:
        self._tokens = tokens

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        return next(
            (token for token in self._tokens.values() if token.token_hash == token_hash),
            None,
        )

    async def get_by_token_hash_for_update(self, token_hash: str) -> PasswordResetToken | None:
        return await self.get_by_token_hash(token_hash)

    async def save(self, token: PasswordResetToken) -> PasswordResetToken:
        self._tokens[token.reset_token_id] = token
        return token


class _FakeInvitationRepository:
    def __init__(self, invitations: dict[UUID, UserInvitation]) -> None:
        self._invitations = invitations

    async def get_by_id(self, invitation_id: UUID) -> UserInvitation | None:
        return self._invitations.get(invitation_id)

    async def get_by_token_hash(self, token_hash: str) -> UserInvitation | None:
        return next(
            (
                invitation
                for invitation in self._invitations.values()
                if invitation.token_hash == token_hash
            ),
            None,
        )

    async def get_by_token_hash_for_update(self, token_hash: str) -> UserInvitation | None:
        return await self.get_by_token_hash(token_hash)

    async def get_by_workspace_and_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
    ) -> UserInvitation | None:
        return next(
            (
                invitation
                for invitation in self._invitations.values()
                if invitation.workspace_id == workspace_id
                and invitation.email_normalized == email_normalized
            ),
            None,
        )

    async def save(self, invitation: UserInvitation) -> UserInvitation:
        self._invitations[invitation.invitation_id] = invitation
        return invitation


class _FakeAuthAuditLogRepository:
    def __init__(self) -> None:
        self.logs: list[AuthAuditLog] = []

    async def append(self, audit_log: AuthAuditLog) -> AuthAuditLog:
        self.logs.append(audit_log)
        return audit_log


class _FakeEmailProvider:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        return f"email::{len(self.messages)}"


class _FakePasswordHasher:
    async def hash_password(self, password: str) -> str:
        return f"hashed::{password}"

    async def verify_password(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return password_hash.startswith("legacy::")


class _FakeOpaqueTokenService:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)

    def generate_token(self) -> OpaqueToken:
        plaintext = self._tokens.pop(0)
        return OpaqueToken(plaintext=plaintext, token_hash=self.hash_token(plaintext))

    def hash_token(self, token: str) -> str:
        return f"hash::{token}"

    def verify_token(self, token: str, token_hash: str) -> bool:
        return self.hash_token(token) == token_hash


class _FakeAccessTokenService:
    def __init__(self) -> None:
        self._issued_tokens: dict[str, DecodedAccessToken] = {}
        self._counter = 0

    def issue_token(
        self,
        subject: AccessTokenSubject,
        *,
        issued_at: datetime,
        expires_at: datetime,
        token_id: UUID | None = None,
    ) -> IssuedAccessToken:
        self._counter += 1
        resolved_token_id = token_id or UUID(f"00000000-0000-0000-0000-{self._counter:012d}")
        token = f"access::{self._counter}"
        decoded = DecodedAccessToken(
            token_id=resolved_token_id,
            subject=subject,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._issued_tokens[token] = decoded
        return IssuedAccessToken(
            token=token,
            token_id=resolved_token_id,
            subject=subject,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def decode_token(self, token: str) -> DecodedAccessToken:
        return self._issued_tokens[token]


def _user(
    *,
    user_id: UUID = USER_ID,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    return User(
        user_id=user_id,
        email="user@example.com",
        email_normalized="user@example.com",
        full_name="User Example",
        status=status,
        email_verified_at=NOW,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _workspace(
    *,
    workspace_id: UUID = WORKSPACE_ID,
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE,
) -> Workspace:
    return Workspace(
        workspace_id=workspace_id,
        name=f"Workspace {workspace_id}",
        status=status,
        default_timezone="UTC",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _membership(
    *,
    membership_id: UUID = MEMBERSHIP_ID,
    workspace_id: UUID = WORKSPACE_ID,
    user_id: UUID = USER_ID,
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.ASSIGNED_AGENT,
    status: WorkspaceMembershipStatus = WorkspaceMembershipStatus.ACTIVE,
) -> WorkspaceMembership:
    return WorkspaceMembership(
        membership_id=membership_id,
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        status=status,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _credential(
    *,
    password_hash: str,
    failed_attempt_count: int = 0,
) -> PasswordCredential:
    return PasswordCredential(
        user_id=USER_ID,
        password_hash=password_hash,
        password_changed_at=NOW - timedelta(days=1),
        failed_attempt_count=failed_attempt_count,
        locked_until=None,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _refresh_session(
    *,
    session_id: UUID = SESSION_ID,
    token_hash: str = "hash::refresh-token",
    revoked_at: datetime | None = None,
    revoked_reason: RefreshSessionRevocationReason | None = None,
) -> RefreshSession:
    return RefreshSession(
        session_id=session_id,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        refresh_token_hash=token_hash,
        family_id=FAMILY_ID,
        rotated_from_session_id=None,
        expires_at=NOW + timedelta(days=30),
        revoked_at=revoked_at,
        revoked_reason=revoked_reason,
        created_at=NOW - timedelta(days=1),
        last_used_at=None,
    )


def _invitation(
    *,
    token_hash: str = "hash::invite-token",
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.ASSIGNED_AGENT,
) -> UserInvitation:
    return UserInvitation(
        invitation_id=INVITATION_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        email="user@example.com",
        email_normalized="user@example.com",
        role=role,
        token_hash=token_hash,
        expires_at=NOW + timedelta(days=7),
        accepted_at=None,
        revoked_at=None,
        created_by_user_id=ADMIN_ID,
        created_at=NOW - timedelta(days=1),
    )


def _reset_token(*, token_hash: str) -> PasswordResetToken:
    return PasswordResetToken(
        reset_token_id=RESET_TOKEN_ID,
        user_id=USER_ID,
        token_hash=token_hash,
        expires_at=NOW + timedelta(minutes=30),
        used_at=None,
        created_at=NOW - timedelta(minutes=1),
    )


def _actor(
    *,
    user_id: UUID = ADMIN_ID,
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.BROKERAGE_ADMIN,
    active_workspace_id: UUID = WORKSPACE_ID,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=user_id,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=active_workspace_id,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[object, object, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
