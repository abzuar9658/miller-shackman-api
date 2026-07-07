from collections.abc import Coroutine
from typing import TypeVar
from uuid import UUID

from app.application.use_cases.authentication import AuthReasonCode
from app.application.use_cases.workspace import (
    CreateWorkspaceStatus,
    ListWorkspaceUsersStatus,
    ResendInvitationStatus,
    UpdateUserStatusStatus,
    UpdateWorkspaceMembershipStatus,
    create_workspace,
    list_workspace_users,
    resend_invitation,
    update_user_status,
    update_workspace_membership,
)
from app.domain.identity import (
    AuthAuditEventType,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    INVITATION_ID,
    MEMBERSHIP_ID,
    NOW,
    SECOND_WORKSPACE_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _Dependencies,
    _invitation,
    _membership,
    _user,
    _workspace,
)

T = TypeVar("T")

NEW_WORKSPACE_ID = UUID("00000000-0000-0000-0000-00000000000c")
NEW_USER_ID = UUID("00000000-0000-0000-0000-00000000000d")
NEW_MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-00000000000e")


def test_create_workspace_creates_workspace_and_admin_membership() -> None:
    deps = _Dependencies()
    actor = _actor()

    result = _run(
        create_workspace(
            actor=actor,
            name="New Brokerage",
            default_timezone="America/Chicago",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == CreateWorkspaceStatus.CREATED
    assert result.workspace is not None
    assert result.workspace.name == "New Brokerage"
    assert result.workspace.status == WorkspaceStatus.ACTIVE
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.BROKERAGE_ADMIN
    assert result.membership.status == WorkspaceMembershipStatus.ACTIVE
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.WORKSPACE_CREATED


def test_create_workspace_rejects_without_permission() -> None:
    deps = _Dependencies()
    actor = _actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT)

    result = _run(
        create_workspace(
            actor=actor,
            name="New Brokerage",
            default_timezone="America/Chicago",
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == CreateWorkspaceStatus.REJECTED
    assert result.reasons == (AuthReasonCode.PERMISSION_DENIED,)


def test_list_workspace_users_returns_users() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[ADMIN_ID] = _user(user_id=ADMIN_ID)
    deps.memberships[MEMBERSHIP_ID] = _membership(
        membership_id=MEMBERSHIP_ID,
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        list_workspace_users(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
        ),
    )

    assert result.status == ListWorkspaceUsersStatus.FOUND
    assert len(result.users) == 1
    assert result.users[0].user.user_id == ADMIN_ID


def test_list_workspace_users_rejects_without_membership() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    actor = _actor(active_workspace_id=SECOND_WORKSPACE_ID)

    result = _run(
        list_workspace_users(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            user_repository=deps.user_repository,
        ),
    )

    assert result.status == ListWorkspaceUsersStatus.REJECTED
    assert result.reasons == (AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,)


def test_resend_invitation_sends_new_email() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )
    deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::old-token")
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        resend_invitation(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            invitation_id=INVITATION_ID,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            invitation_repository=deps.invitation_repository,
            audit_log_repository=deps.audit_log_repository,
            opaque_token_service=deps.opaque_token_service,
            email_provider=deps.email_provider,
            now=NOW,
        ),
    )

    assert result.status == ResendInvitationStatus.RESENT
    assert result.invitation is not None
    assert result.invitation.token_hash == "hash::invite-token"
    assert len(deps.email_provider.messages) == 1
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.INVITATION_RESENT


def test_update_workspace_membership_changes_role() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.ASSIGNED_AGENT)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=WorkspaceMembershipRole.MANAGER,
            membership_status=None,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.role == WorkspaceMembershipRole.MANAGER
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.ROLE_CHANGED


def test_update_workspace_membership_disables_membership() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership()
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_workspace_membership(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=None,
            membership_status=WorkspaceMembershipStatus.DISABLED,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateWorkspaceMembershipStatus.UPDATED
    assert result.membership is not None
    assert result.membership.status == WorkspaceMembershipStatus.DISABLED
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.MEMBERSHIP_DISABLED


def test_update_user_status_disables_user() -> None:
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[USER_ID] = _user()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    actor = _actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)

    result = _run(
        update_user_status(
            actor=actor,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            user_status=UserStatus.DISABLED,
            user_repository=deps.user_repository,
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            now=NOW,
        ),
    )

    assert result.status == UpdateUserStatusStatus.UPDATED
    assert result.user is not None
    assert result.user.status == UserStatus.DISABLED
    assert deps.audit_log_repository.logs[-1].event_type == AuthAuditEventType.USER_DISABLED


def _run[T](coroutine: Coroutine[object, object, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
